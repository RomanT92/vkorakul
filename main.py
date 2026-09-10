                    if doc_url:
                        parse_result = parse_bank_file_with_ai(doc_url, doc_ext)
                        if parse_result.get("status") == "SUCCESS":
                            operations = parse_result.get("operations", [])
                            if not operations:
                                send_vk_message(
                                    user_id,
                                    "⚠️ Файл прочитан, но в нем не найдено операций с суммами больше 0.\n"
                                    "Проверьте, что в выписке есть заполненные колонки с датой и суммой.",
                                    get_main_keyboard(user_id)
                                )
                                continue

                            send_vk_message(user_id, f"✅ Извлек {len(operations)} операций.\n⚡ Анализирую и сохраняю в базу данных...")
                            stats = import_parsed_operations(internal_uid, operations)
                            
                            report_msg = (
                                f"📊 **Результат импорта:**\n"
                                f"• Всего операций: {stats['total']}\n"
                                f"• Автоматически распределено: {stats['verified']}\n"
                                f"• Требует проверки: {stats['needs_review']}"
                            )
                            
                            if user_id in user_states and user_states[user_id].get("state") == "wait_import_file":
                                del user_states[user_id]
                            
                            if stats['needs_review'] == 0:
                                send_vk_message(user_id, report_msg + "\n\n🎉 Все операции распределены идеально!", get_main_keyboard(user_id))
                            else:
                                report_msg += (
                                    f"\n\n📥 Нажмите кнопку «Разобрать операции ({stats['needs_review']})», "
                                    f"чтобы распределить оставшиеся статьи пакетами по 7 штук!"
                                )
                                send_vk_message(user_id, report_msg, get_main_keyboard(user_id))
                        else:
                            send_vk_message(user_id, f"❌ Не удалось разобрать файл: {parse_result.get('message')}", get_main_keyboard(user_id))
